# Бета-канал (инструкция для тестировщиков)

Бета-версии интеграции **«Аквилон InHome»** распространяются через **приватный
репозиторий** `Gakuzi/akvilon_home` (ветка `hacs`). Стабильные версии — через
этот публичный репозиторий.

## Как подключить бета-источник в HACS

1. **Создайте Personal Access Token (PAT)** на GitHub:
   Settings → Developer settings → Personal access tokens → Generate new token,
   scope: **repo**.

2. **Дайте токен HACS** в Home Assistant:
   HACS → ⋮ → Настройки → поле **GitHub token** → вставьте токен → Сохранить.

3. **Добавьте приватный репозиторий как Custom repository:**
   HACS → ⋮ → **Custom repositories** → URL
   `https://github.com/Gakuzi/akvilon_home` → Тип: **Integration** → **Add**.

4. Появится **Аквилон InHome** → выберите канал **Beta** → **Download** →
   перезапустите Home Assistant.

> Если HACS показывает «The version ... can not be used with HACS» — обновите
> список версий (перезагрузите HACS) и выбирайте самую свежую `*-betaN`.
> Тег `v1.6.0-beta1` (старая, несовместимая структура) удалён.

## Что нового в бета-версиях

Смотрите [CHANGELOG.md](CHANGELOG.md).