# Этап 12 — MCP chrome + Approve (PySide6)

Ты исполнитель **только этапа 12**. Launchers — этап 13; удаление web UI — 14.

## Обязательное чтение

- `AGENTS.md`, `doc/pyside6-migration.md`, `doc/mcp-api.md`, approve gate

## Сделать

1. Per-tab MCP ON/OFF, Copy URL, Enable/Disable all.
2. Approve checkbox на chrome вкладки; `QDialog` + countdown (default 3 с) на write/run.
3. Status bar: MCP listening / client (без секретов/адресов).
4. Контракт MCP HTTP/stdio не менять.

## Критерий приёмки

- [ ] Live MCP write → modal → accept/timeout как в v1.
- [ ] Token scope и ошибки `client_busy` / `unauthorized` без регрессий.

## Отчёт оркестратору

Сделано / как проверить (`check_mcp_live` / Cursor) / отклонения.
