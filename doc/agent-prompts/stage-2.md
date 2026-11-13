# Этап 2 — Session Manager + SSH (headless)

Ты исполнитель **только этапа 2**. Не начинай MCP server / UI / launchers.

## Обязательное чтение

- `AGENTS.md`, `doc/data-model.md` (Session runtime), `doc/implementation-plan.md` → этап 2

## Сделать

1. Встроенный SSH → интерактивный shell channel (Paramiko или async ssh — выбрать и зафиксировать).
2. Runtime Session: alias (ручной + авто `host-user-N`), статусы `connecting|live|disconnected|closed`.
3. Буфер вывода + cursor для последующего `session_read`.
4. `write` в PTY; disconnect; reconnect по id сущностей vault (секреты только внутри core).
5. Интеграционный способ проверки (тест/скрипт; Docker/WSL sshd или документированный ручной хост).

Красивый xterm не нужен — байты/текст.

## Критерий приёмки

- [ ] Открыть сессию, увидеть echo в буфере, write доставляет команду.
- [ ] Reconnect после обрыва восстанавливает live без утечки секретов наружу API сессии.

## Отчёт оркестратору

Сделано / как прогнать интеграцию / библиотека SSH / отклонения.
