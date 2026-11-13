# Этап 9 — Каркас PySide6 + unlock

Ты исполнитель **только этапа 9**. CRUD дерева, вкладки SSH, MCP chrome — этапы 10+.

## Обязательное чтение

- `AGENTS.md`, `doc/pyside6-migration.md`, `doc/ui-guidelines.md`, `doc/architecture.md`

## Сделать

1. Добавить зависимость PySide6 (`desktop` extra допустим).
2. Пакет презентации (`hostskeeper.desktop` или согласованное имя): `QMainWindow` с toolbar / left panel / tabs / status bar (заглушки содержимого).
3. Диалог unlock → существующий vault/core; lock сбрасывает UI-состояние.
4. Точка входа: Qt по умолчанию или `--ui qt`; web API сохранить как `--ui web` без новых фич.
5. MCP HTTP в фоне как сейчас (без браузера).

## Критерий приёмки

- [ ] После unlock видно главное окно Royal-layout.
- [ ] `pytest` по core/MCP зелёный.

## Отчёт оркестратору

Сделано / как запустить Qt / отклонения от `doc/pyside6-migration.md`.
