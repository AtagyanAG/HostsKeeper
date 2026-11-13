# Этап 11 — SSH-вкладки + терминал (PySide6)

Ты исполнитель **только этапа 11**. MCP chrome / Approve — этап 12; launchers — 13.

## Обязательное чтение

- `AGENTS.md`, `doc/pyside6-migration.md`, `doc/ui-guidelines.md`, session/API core

## Сделать

1. Open Tab из дерева/тулбара → `SessionManager` → вкладка с alias.
2. Минимальный терминал (вывод буфера + ввод); обновление через signals/`QTimer`, не HTTP UI.
3. Reconnect / Disconnect / Close; статусы live / disconnected / closed.
4. Поток: Paramiko I/O вне GUI-thread.

## Критерий приёмки

- [ ] Lab SSH: вывод виден в вкладке; клавиатура доставляет команды.
- [ ] Reconnect восстанавливает live без утечки секретов в UI chrome.

## Отчёт оркестратору

Сделано / как проверить на lab / отклонения.
