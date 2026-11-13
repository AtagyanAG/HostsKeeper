# Этап 4 — Approve

Ты исполнитель **только этапа 4**.

## Обязательное чтение

- `AGENTS.md`, `doc/mcp-api.md`, `doc/implementation-plan.md` → этап 4

## Сделать

1. Per-session: `approve_required`, `approve_timeout_sec` (default 3).
2. Очередь pending для `session_write` (и заготовка под `scripts_run`).
3. Accept / reject / timeout → ошибка клиенту; без accept байты **не** в PTY.
4. Хуки/события для будущего UI; до UI — CLI approve или test auto-mode (явно документировать).

## Критерий приёмки

- [ ] При approve on запись без подтверждения не попадает в PTY.
- [ ] Timeout → `approve_timeout` (или согласованный код), PTY чист от этой записи.

## Отчёт оркестратору

Сделано / как симулировать approve в тестах / отклонения.
