# Этап 5 — Скрипты в MCP

Ты исполнитель **только этапа 5**. UI-формы параметров не делать.

## Обязательное чтение

- `AGENTS.md`, `doc/mcp-api.md`, `doc/data-model.md` (Script), `doc/implementation-plan.md` → этап 5

## Сделать

1. Tools: `scripts_list`, `scripts_get`, `scripts_create`, `scripts_update`, `scripts_delete`, `scripts_run`.
2. Подстановка `{{params}}`; required/default; ошибки `missing_param` / `unknown_placeholder`.
3. Скрипты в том же encrypted vault.
4. CRUD **без** approve; `scripts_run` — через тот же approve, что write.
5. HTTP: run только в token-сессию; stdio: указать session.

## Критерий приёмки

- [ ] Создать скрипт через MCP, run с params → в PTY уходит подставленный текст.
- [ ] HTTP не может направить run в чужую сессию.

## Отчёт оркестратору

Сделано / примеры вызовов tools / отклонения.
