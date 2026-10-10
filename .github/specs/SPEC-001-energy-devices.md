# SPEC-001 — Энергетика + устройства (feature/entities-device-energy)

- **Статус:** зафиксирована в коде (коммит `0216ee6`, ветка `feature/entities-device-energy`).
- **Роль:** приёмка/доводка перед сведением в `main`.
- **Дата:** 2026-10-10.

## Цель
Интегрировать счётчики квартиры в «Энергопанель» HA и собрать сущности по
устройствам (камера/калитка/домофон/счётчик/сервер) для чистого представления
в реестре устройств.

## Объём (уже сделано)
- `energy.py`: `async_setup_energy` — программная запись `energy_sources`
  (электричество день/ночь как `grid`, вода холод/горяч, отопление как `water`).
- `config_flow`: новый шаг `tariffs` (тарифы Архангельск по умолчанию:
  элек-во день 8.67 / ночь 3.91; вода 0.0). Показывается только если есть счётчики.
- `const.py`: `_devid()` + `server/camera/gate/intercom/meter_dev_id`.
- `device_info` на всех платформах; `_attr_state_class = "total_increasing"` у счётчиков.
- Автозапуск веб-панели камер (viewer) на порту 8090.
- Дашборд без custom JS-карточки (vertical-stack + picture-entity).
- Исключение дублей кнопок калитка/домофон.
- Тесты `test_energy_dev.py`, расширения `test_protocol.py`.

## Точки интеграции
`__init__.py` (вызов async_setup_energy + retries дашборда), `sensor.py`/`camera.py`/
`button.py`/`binary_sensor.py` (device_info), `config_flow.py` (шаг tariffs).
Контракт `energy_sources` — по `homeassistant.components.energy`.

## Edge Cases
- Нет счётчиков → шаг тарифов пропускается, entry создаётся без него.
- Чужие `energy_sources` не перетираются (только добавляем каналы к существующему grid).
- `price <= 0` → тариф не пишется в источник (вода/тепло без цены).
- `energy` manager недоступен → предупреждение, не падение.
- Вода: два РАЗНЫХ счётчика = два источника (несколько линий воды), без дублей.

## Зависимости / тесты
`homeassistant.components.energy` (core). Тесты голые: `test_energy_dev.py` (78 строк),
`test_protocol.py`. 97 тестов в сумме зелёные.

## Критерии готовности (qa + doc)
- [ ] `python3 -m compileall` чисто.
- [ ] 97+ тестов прошли, покрытие >= 60%.
- [ ] В локальном HA (ha-local) пересоздан config entry: шаг тарифов появляется,
      `energy_sources` заполнен, сущности привязаны к устройствам.
- [ ] CHANGELOG/README с описанием энергетики; docstring в `energy.py`.
- [ ] Секретов нет (IP/PASS/token — плейсхолдеры).