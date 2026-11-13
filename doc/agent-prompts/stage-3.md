# Этап 3 — MCP: сессии

Ты исполнитель **только этапа 3** (скрипты CRUD — этап 5; approve — этап 4).

## Обязательное чтение

- `AGENTS.md`, `doc/mcp-api.md`, `doc/implementation-plan.md` → этап 3

## Сделать (порядок)

1. **Сначала stdio:** tools `session_info`, `session_list`, `session_read`, `session_subscribe`, `session_write` для всех mcp-enabled сессий.
2. Per-tab token: enable/disable MCP на сессии; отзыв token при disable/close tab.
3. **Затем HTTP LAN:** bind на LAN; URL с token; scope = одна вкладка; **1 клиент на token** (`client_busy`).
4. Ошибки: `unauthorized`, `disconnected`, `client_busy`, …
5. Тесты: ответы MCP **не** содержат host/user/password/key/address.

`session_info` по token должен отдавать **alias**.

## Критерий приёмки

- [ ] Stdio: list/read/write на mcp-enabled сессии.
- [ ] HTTP: connect по URL+token, узнать alias, read/write.
- [ ] Второй клиент на тот же token — отказ.
- [ ] Тесты на отсутствие секретов в payload — зелёные.

## Отчёт оркестратору

Сделано / SDK и транспорт HTTP / как подключить Cursor / отклонения.
