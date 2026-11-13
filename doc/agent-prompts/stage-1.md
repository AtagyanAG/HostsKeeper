# Этап 1 — Vault

Ты исполнитель **только этапа 1**. Не начинай SSH/MCP/UI.

## Обязательное чтение

- `AGENTS.md`, `doc/data-model.md`, `doc/implementation-plan.md` → этап 1

## Сделать

1. Создание и открытие vault по паролю (KDF + AEAD; формат выбрать и кратко зафиксировать в отчёте / при необходимости в doc).
2. CRUD: Host, Address, Credential, Script по data-model.
3. Defaults у Host (`default_address_id`, `default_credential_id`).
4. Persist на диск; переживает рестарт процесса.
5. Юнит-тесты: round-trip; неверный пароль → отказ; secret-поля не в `repr`.

CLI или тонкий API для проверки — ок. UI и backup — не делать.

## Критерий приёмки

- [ ] Создать host+address+credential+script, закрыть процесс, открыть снова — данные на месте.
- [ ] Тесты секретов/пароля зелёные.

## Отчёт оркестратору

Сделано / команды тестов / выбранный формат контейнера / отклонения.
