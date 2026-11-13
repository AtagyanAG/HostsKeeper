# Этап 14 — Вывод web UI + документация

Ты исполнитель **только этапа 14**. Не начинать post-v1 фичи.

## Обязательное чтение

- `AGENTS.md`, `doc/pyside6-migration.md`, `doc/regression-checklist.md`, `doc/user-guide.md`

## Сделать

1. Убрать static web UI и UI-only FastAPI-роуты из продукта; MCP HTTP оставить.
2. Точка входа по умолчанию — PySide6.
3. Обновить `architecture.md`, `user-guide.md`, `regression-checklist.md`, `dev-setup.md`, README.
4. Прогнать чеклист на Qt (ручной) + `pytest`.

## Критерий приёмки

- [ ] Продуктовый сценарий без браузера.
- [ ] Документы соответствуют факту; чеклист отмечен.

## Отчёт оркестратору

Сделано / что удалено / как проверить / эскалации (Cursor LAN).
