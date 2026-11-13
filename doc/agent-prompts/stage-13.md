# Этап 13 — Launchers в Qt

Ты исполнитель **только этапа 13**. Retire web UI — этап 14.

## Обязательное чтение

- `AGENTS.md`, `doc/pyside6-migration.md`, launchers module, этап 7 поведение

## Сделать

1. Кнопки/меню PuTTY и WinSCP → `launch_putty` / `launch_winscp`.
2. OpenSSH → `.ppk` как в этапе 7; пароль не в cmdline.
3. Launchers не создают MCP-сессии и не попадают в MCP session list.

## Критерий приёмки

- [ ] Из Qt открываются PuTTY и WinSCP к выбранной паре Address+Credential.

## Отчёт оркестратору

Сделано / пути обнаружения / отклонения.
